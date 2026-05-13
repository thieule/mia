# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

- Tony uses Fine-grained GitHub tokens.
- To create repos, tokens need Administration and Contents (Read/Write) permissions for repository operations.
- Private repo 404 errors: ensure the specific repository is selected in token settings.

## Preferences

- User prefers module-by-module work (currently focused on Agile Studio).
- Public documentation must remain generic (no mention of "Tada" or "Phú").

## Project Context

Use one block per project (fill from **Agile Studio MCP** or the user; do not hard-code in prompts):

```text
## Project: <project_code_or_slug>

- github_repository: owner/repo (from MCP or user)
- documents_storage_path / WORK_ROOT: …
- default_branch: …
- workflow notes (branches, where to push): …
```

Do **not** link or assume paths to Agile Studio sources in git — deployment may omit that tree. Reload from **MCP** + this file when unsure.

## Project: Agile Studio

- github_repository: thieule/mia (Primary), thieule/tada-demo (Documentation)
- documents_storage_path: docs/
- workflow notes: No direct commits to master or main; use branches and Pull Requests for review.
- Scope: Technical designs for all project stories (including #1-#9, #23, #24) are complete.
- Storage Strategy: Git for Markdown source of truth; Neo4j Aura for Graph-RAG; Elasticsearch for vector search (384 dimensions); MySQL for metadata.
- Technical Design Locations:
    - Stories #2, #3, and #8: Stored in Git at `projects/agile-studio/docs/`.
    - Story #6: Technical design approved. Uses Neo4j Aura (Graph-RAG), Elasticsearch, MySQL. ADR Standard: MADR v2.1.0. Implementation paused pending cost approval.
    - Story #9: In the Wiki but missing from Git.
    - Technical designs must be stored in the project Wiki, not in story comments.
- Story Details:
    - Story #3 (Roadmap/Gantt): Status: Backlog. Associated documents set to Draft. Uses frappe-gantt with auto-scheduling.
    - Story #6 (Knowledge Management System): Features Data Ingestion Pipeline (Webhooks/Git), React Force Graph visualization, and MCP Second Brain Server tools.
    - Story #7 (Git Integration): Status: Current.
    - Story #8 (MCP Server): Status: current_started (Implementation Priority). Reporter: Tony.
    - Story #9 (In-doc Commenting): Uses Text Anchoring (dom-anchor-text-quote) for position maintenance.
    - Story #10 (Real-time Events): Status: Draft. Reporter: Tony. Uses the existing WebSocket mechanism in chat-service. Triggers need integration in `agile_hub/crud.py` and `router.py`.
    - Story #24 (Workflows Automation): Status: Current. Uses an IF-AND-THEN rule engine model.
    - Story #25 (Roadmap/Gantt View): Status: Current.
    - Story #26 (AI Insights): Uses Monte Carlo simulations for forecasting and Sentiment Analysis for comments.
    - Story #27 (Experience Store): Uses JSONB diffs to track user corrections and refine AI behavior.
    - Story #28 (Project Second Brain): Status: Current. Technical design: "Project Second Brain & Codebase Intelligence" (ID: 29f3fe98-07d5-478d-86d0-890bd47313f7).
        - Approach: Code Ingestion Pipeline (logic-based chunking), Hybrid Indexing (Elasticsearch vector search, Neo4j code graph).
        - Tech: Tree-sitter for incremental static analysis via GitHub webhooks.
        - Schema: Nodes (Module, Service, Class, Interface, Function, File); Relationships (CONTAINS, DEFINES, CALLS, INHERITS_FROM, IMPORTS).
        - Features: Architecture Visualization, Codebase Understanding, Implementation Assistance.
        - Note: Requires explicit approval from @tony before starting implementation tasks.
    - Story #29 (Git Integration): Features Commit Linking, AI PR Review, and Traceability Matrix.
- Technical Architecture:
    - `agile_hub` module: `agile-studio/agile_hub/`. Uses custom `MUInt` type for MySQL UNSIGNED compatibility in SQLite.
    - `StoryStatus` Literal: `icebox`, `backlog`, `current`, `done`.
    - `chat-service` (NestJS): Uses Socket.io and `ChatGateway` for real-time broadcasts.
    - Internal event broadcasting: `POST /api/chat/internal/story-events/broadcast`.
    - `agile_hub/chat_sync.py`: Uses `urllib` with 8s timeout for notifications.
    - Environment: API port 9120, Web UI port 5175, MySQL `agile_studio` (3306/3307).
    - Key env vars: `AGILE_DATABASE_URL`, `AGILE_EMBEDDING_HTTP_URL`, `AGILE_EMBEDDING_HTTP_KEY`, `AGILE_JWT_SECRET`.
    - `SECOND_BRAIN_EMBEDDING_FALLBACK=1`: Local BLAKE2b hashing (384-dim) for deterministic embeddings.
    - Use FastAPI `BackgroundTasks` for event triggers to avoid blocking API responses.
    - Extracted `agile_hub` models: Wiki doc "Agile Hub: Models & Schemas" (slug: `agile-hub-models-schemas`).
    - `mcp_server` directory is NOT at `agile-studio/mcp_server`.
- API & Validation:
    - Rules: Title length 5-255 chars, auto-generated kebab-case slugs.
    - Error codes: DOC_NOT_FOUND, EMBEDDING_FAILURE, SYNC_CONFLICT.
    - Uses `temp_schemas.py` to store extracted code for reliable parsing of Pydantic schemas.
- Live MCP tool groups: Wiki, Agile, Collaboration, and Project/Member tools.
- AI Insights: Monte Carlo simulations for forecasting; LLM-based sentiment analysis.



## Important Notes

- Repos and paths are **not** fixed in agent prompts — refresh from MCP + this file + chat when unsure.
- Gantt Chart implementation requires Virtual Scrolling for performance when displaying >100 stories.
- `agile_story_task_create` tool has a bug (missing `story_id` default); embed task lists in Story Descriptions as a workaround.
- Use `ref: #{story-id}` in commit bodies to enable automated linking via Webhooks.
- Regex pattern for primary commit linking: `/(?:ref:?\s*#)(\d+)/gi`.
- Fallback regex pattern for story-keys: `/^([a-z0-9-]+):/i`.

---

*This file is automatically updated by nanobot when important information should be remembered.*
