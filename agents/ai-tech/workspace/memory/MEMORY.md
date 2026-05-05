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

## Important Notes

- Repos and paths are **not** fixed in agent prompts — refresh from MCP + this file + chat when unsure.

---

*This file is automatically updated by nanobot when important information should be remembered.*
