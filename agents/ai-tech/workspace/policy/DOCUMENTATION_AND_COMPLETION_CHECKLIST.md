# Documentation updates and completion checklist (Mia tech)

**Status:** Human-maintained policy under `policy/`. Mia tech **must read and follow** this file. It **must not** edit files in `policy/` without an approved workflow.

---

## 1. Purpose

After implementation work, documentation must stay **accurate** and each closure must include a **completion checklist** plus any **supplementary** docs the change warrants. **Per project or module**, long-lived documentation lives under that unit’s own **`docs/`** directory.

---

## 2. Where documentation lives

Follow **`docs/LAYOUT_PROJECT_DOCUMENTATION.md`** for the `projects/<slug>/` tree (and repo equivalents). **Do not** leave module-specific prose only in chat when policy expects it under **`projects/<slug>/docs/`** (note any mapping in the checklist if your repo differs).

---

## 3. What to update before claiming “done”

Before the same “done” message allowed by **`TESTING_AND_DEFINITION_OF_DONE.md`**, the agent **must**:

| Step | Action |
|------|--------|
| 1 | **Review** which user-visible or maintainer-facing docs are **stale** because of the change (README, `docs/`, OpenAPI, comments that are contract-level, config examples). |
| 2 | **Update** those files under the correct **`<slug>`** tree or repo root. All new or updated prose must be **English** per **`CODE_COMMENTS_AND_ERRORS_ENGLISH.md`** §3 unless an admin exception exists. |
| 3 | **Add supplementary docs** when the change introduces new behaviour, limits, migration steps, or ops runbooks — place them under **`projects/<slug>/docs/`** (or repo-standard paths), in **English**. |
| 4 | **Write or update** **`projects/<slug>/docs/COMPLETION_CHECKLIST.md`** for this task (see §4). If the work spans multiple slugs, use one checklist file **per slug** or one file with clearly separated sections—pick one convention per team and stick to it. |
| 5 | In the **final reply** to the user, **summarise** doc paths touched and **paste or link** the checklist status (all required boxes checked). |

If **no** `projects/<slug>` applies (single-repo change only), put **`COMPLETION_CHECKLIST.md`** next to the change (e.g. repo `docs/` or `agent/` per team rule) and list that path in the reply.

---

## 4. Completion checklist (required content)

Each **`COMPLETION_CHECKLIST.md`** for a finished task **must** include at least:

- [ ] **Scope** — short description of what was delivered (link to ticket/ADR if any).
- [ ] **Code & tests** — pytest run result summary (or pointer to `run_id` / log); tests added/updated listed.
- [ ] **English in repo** — **comments**, **docstrings**, **error/log messages**, and **this task’s documentation** (README, `docs/`, checklist body) comply with **`CODE_COMMENTS_AND_ERRORS_ENGLISH.md`** §2–§3 (or note an admin exception).
- [ ] **Documentation** — bullets listing each file created/updated (`README`, `docs/...`, etc.).
- [ ] **Supplementary docs** — “None” or filenames + one-line purpose.
- [ ] **Risks / follow-ups** — known limitations, TODOs for humans, feature flags.
- [ ] **Admin approval** — reference that **`PRE_IMPLEMENTATION_APPROVAL.md`** was satisfied (who/when if visible in thread).

Teams may extend this list in their own template; Mia tech **must not** claim **done** with empty or missing sections when work was non-trivial.

Optional template copy: **`docs/templates/COMPLETION_CHECKLIST.template.md`** in this workspace.

---

## 5. Exceptions (admin-maintained)

- *(None by default.)*

---

## 6. Cross-references

See **`policy/README.md`**. **`docs/AI_PROJECT_WORKSPACE_SPEC.md`** — `projects/<slug>/` location. **`policy/CODE_COMMENTS_AND_ERRORS_ENGLISH.md`** — English for repo documentation produced here.
