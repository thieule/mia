---
name: second-brain-decisions
description: Consult Second Brain (Neo4j + ES) for prior decisions, lessons, and documented context before stories, acceptance criteria, or technical design.
always: true
---

# Second Brain — prior decisions and experience

The **second-brain** MCP server exposes organizational memory: ADRs (`Decision`), lessons (`LessonLearned`), feedback, wiki-derived chunks, commits (stub), and ingested Agile entities. Use it **before** proposing substantial product or engineering work so recommendations align with recorded intent.

## When to query (mandatory habit)

- **Mia BA:** Before creating or reshaping a **story**, **epic-level scope**, or **acceptance criteria** that might duplicate, reverse, or weaken an earlier decision.
- **Mia Tech:** Before **technical design**, stack choices, migrations, breaking API changes, or implementation plans that could conflict with an existing ADR or lesson.

If the task is trivial (typo, logging, obvious bugfix) and unrelated to past architecture or product direction, you may skip; when in doubt, run a quick search.

## Required inputs

- **`project_id`** (integer): Resolve from the current Agile Studio context (story/task/project tools, user message, or working-queue payload). Never guess; if unknown, ask or obtain via `agile_*` tools before calling Second Brain.
- **Search query**: Short natural-language phrases (features, component names, constraints, “why we chose X”).

## Recommended workflow

1. **`brain_search_knowledge`** — `query` = distilled problem + domain terms; `project_id` = resolved id; `top_k` 8–15. Optionally `scope` / `visibility` if the user specified org-wide vs project-only context.
2. If hits mention interesting **`ref`** values (e.g. `p3:decision:…`, `p3:lesson:…`, `p3:document:…`): call **`brain_get_neighborhood`** with `depth` 2 to see linked stories, comments, or supersession chains.
3. For structured checks (e.g. “all decisions linked to this story”, “what superseded what”): **`brain_query_graph`** with **read-only** Cypher. Keep result sets small.

## After retrieval

- **Summarize** relevant prior decisions or lessons in your reply (neutral tone; cite `ref` or title when useful).
- If nothing relevant appears, say so explicitly; do not invent institutional memory.
- If the user’s request **conflicts** with a stored decision, call it out and suggest confirming with humans or superseding via the proper workflow (`brain_supersede_decision` / new ADR), rather than silently overriding.

## Writing back (only when asked or clearly appropriate)

- **`brain_remember_decision`** — formalize a new ADR when the user or task asks to record architecture/product choice; include `story_ref` when tied to a story.
- **`brain_remember_lesson`** / **`brain_feedback_create`** — after incidents or retrospectives when capture is requested.
- **`brain_extract_lesson_from_text`** — optional structured extraction from discussion text before persisting.

Do not spam writes: prefer search-first; persist only when there is a clear, durable outcome to record.
