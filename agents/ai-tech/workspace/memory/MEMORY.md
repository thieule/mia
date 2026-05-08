# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

- Tony uses Fine-grained GitHub tokens.
- To create repos, tokens need Administration and Contents (Read/Write) permissions.
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

- github_repository: thieule/tada-demo
- documents_storage_path: docs/
- GitHub access key: Renewed and connectivity verified via test branch.
- Scope: Technical designs for all project stories (including #1-#9, #23, #24) are complete.
- Storage Strategy: Git for Markdown source of truth; Elasticsearch for metadata and semantic search (standardized to 384 dimensions).
- Technical Design Locations:
    - Stories #1, #2, and #3: Stored in Git at `projects/agile-studio/docs/`.
    - Story #6: Draft on Wiki (Neo4j/Graph-RAG), missing from Git. ADR Standard: `a42e7554-1533-4234-8521-63d742d4f40b`. Waiting for Mia BA's spec update.
    - Story #9: In the Wiki but missing from Git.
- Story Details:
    - Story #3 (Roadmap/Gantt): Uses frappe-gantt with auto-scheduling.
    - Story #9 (In-doc Commenting): Uses Text Anchoring (dom-anchor-text-quote) for position maintenance.
    - Story #24 (Workflows Automation): Uses an IF-AND-THEN rule engine model.
- API & Validation:
    - Rules: Title length 5-255 chars, auto-generated kebab-case slugs.
    - Error codes: DOC_NOT_FOUND, EMBEDDING_FAILURE, SYNC_CONFLICT.
- Live MCP tool groups: Wiki, Agile, Collaboration, and Project/Member tools.
- AI Insights: Monte Carlo simulations for forecasting; LLM-based sentiment analysis.
- Knowledge Graph: MySQL for explicit links; Elasticsearch for semantic links.



## Important Notes

- Repos and paths are **not** fixed in agent prompts — refresh from MCP + this file + chat when unsure.

---

*This file is automatically updated by nanobot when important information should be remembered.*
