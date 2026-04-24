# Documentation updates and completion checklist (Mia QC)

**Status:** Human-maintained policy under `admin/`. Mia QC **must read and follow** this file. It **must not** edit files in `admin/` without an approved workflow.

---

## 1. Purpose

After implementation work, documentation must stay **accurate** and each closure must include a **completion checklist** plus any **supplementary** docs the change warrants. **Per project or module**, long-lived documentation lives under that unit’s own **`docs/`** directory.

---

## 2. Per-project / per-module documentation layout

For every directory that represents **one project or one module** (e.g. `WORK_ROOT/projects/<slug>/` per **`docs/AI_PROJECT_WORKSPACE_SPEC.md`**):

```text
projects/<slug>/
├── README.md                 # entry point; link to docs/
├── docs/                     # documentation for THIS project/module only
│   ├── README.md             # optional index for docs/
│   ├── ...                   # ADRs, API notes, runbooks, diagrams as needed
│   └── COMPLETION_CHECKLIST.md   # filled for each completed task (see §4)
└── ...                       # source, tests, etc.
```

- **Do not** put module-specific prose only in the chat transcript — persist important material under **`projects/<slug>/docs/`** (or the repo’s equivalent path if the monorepo uses another layout; then follow that layout and note the mapping in the completion checklist).
- **Repository-wide** docs (e.g. root `README`, `CONTRIBUTING`) must be updated when the change affects them.

If a **`docs/`** folder does not exist yet for `<slug>`, **create** it when the first documentation-heavy change lands there (after admin approval for writes).

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

Teams may extend this list in their own template; Mia QC **must not** claim **done** with empty or missing sections when work was non-trivial.

Optional template copy: **`docs/templates/COMPLETION_CHECKLIST.template.md`** in this workspace.

---

## 5. Exceptions (admin-maintained)

- *(None by default.)*

---

## 6. Relation to other policy

- **`TESTING_AND_DEFINITION_OF_DONE.md`** — pytest green is required before “done”; this file adds **docs + checklist** to the same closure.
- **`docs/AI_PROJECT_WORKSPACE_SPEC.md`** — where **`projects/<slug>/`** lives.
- **`CODE_COMMENTS_AND_ERRORS_ENGLISH.md`** — English for code, errors/logs, and **repository documentation** produced under this policy.

**Full order:** **admin approves → implement (with tests) → pytest green → update docs + fill checklist → report → “done”.**
