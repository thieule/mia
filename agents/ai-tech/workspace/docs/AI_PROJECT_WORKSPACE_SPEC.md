# Spec: Git layout and per-project / per-module directories

> **Location:** `workspace/docs/` — part of the **Mia tech** workspace (`./workspace` in config). The agent reads this file as `docs/AI_PROJECT_WORKSPACE_SPEC.md` (including when `restrictToWorkspace` is enabled).

There is **no fixed GitHub repository** in prompts. Paths and remotes come from **Agile Studio MCP**, from **explicit user answers in chat**, and from **`memory/MEMORY.md`** once the user has supplied them.

---

## 1. Purpose and scope

| Topic | Description |
|--------|-------------|
| **Goal** | A **predictable** directory tree when working with **project-specific** Git roots, **traceable** to the remotes your team actually uses. |
| **In scope** | Where to discover URLs/paths; clone / pull / branches; naming; what the AI may not do without approval. |
| **Out of scope** | CI/CD design, PR policy (team process elsewhere). |

---

## 2. Where repo URL, paths, and branches come from

**Order of precedence:**

1. **Agile Studio MCP** — use **`agile_project_get`** / **`agile_projects_list`** and read fields such as **`settings.github_repository`**, **`documents_storage_path`**, **`storage_overview`**, **`workspace_ref`** (and any others your Hub exposes). Use them as the **source of truth** for where work products and clones should live.
2. **User in chat** — if MCP data is missing, incomplete, or unclear, **ask** for clone URL or `owner/repo`, default branch, and the intended **`WORK_ROOT`** (or confirm `documents_storage_path`).
3. **`memory/MEMORY.md`** — when the user provides URLs, paths, or branch conventions, **record them per project** under a stable heading, for example:

```markdown
## Project: <project_code_or_slug>

- github_repository: owner/repo (from MCP or user)
- clone_url: … (if different from inferred HTTPS)
- default_branch: …
- documents_storage_path / WORK_ROOT: …
- notes: …
```

Reuse that block in later sessions; **do not** invent a default org/repo in prompts.

---

## 3. Recommended directory layout (after you know `GIT_URL`)

**Principle:** one **clone** of the project’s upstream (or agreed canonical remote) plus **child trees** per project/module when the team works multi-unit under one `WORK_ROOT`.

`WORK_ROOT` may be admin-defined and **need not** live inside `workspace/` (subject to `restrictToWorkspace`).

### 3.1. Option A — `upstream/` clone + sibling `projects/`

```text
WORK_ROOT/
├── upstream/
│   └── <upstream-clone>/        # e.g. name from repo; git remote = URL from §2
│       ├── .git/
│       └── ...
└── projects/
    ├── <project-slug-1>/
    │   ├── README.md
    │   ├── docs/                # see policy/DOCUMENTATION_AND_COMPLETION_CHECKLIST.md
    │   └── ...
    └── ...
```

- **`upstream/<upstream-clone>/`**: only content from **`git clone`** / **`git pull`** for the URL from §2 — do **not** change `origin` unless an admin says so.
- **`projects/<slug>/`:** artefacts per project/module; `<slug>` matches **project code** or **module code** (lowercase letters, digits, hyphens). Include **`docs/`** and task **`COMPLETION_CHECKLIST.md`** per team policy.

### 3.2. Option B — Submodule or subtree

If each unit is its **own** Git repo, use **submodule** or **subtree** under `projects/<slug>/`. Run submodule/subtree commands **only** when the user or policy explicitly allows.

---

## 4. Mapping: system ↔ directories

Maintain **one table** (e.g. `WORK_ROOT/PROJECT_INDEX.md` or internal wiki):

| Project / module ID (system) | Display name | Directory `slug` (`projects/…`) | Notes |
|------------------------------|----------------|-----------------------------------|-------|
| *(example)* | *(example)* | `billing-api` | |

Create a **new** `projects/<slug>/` **only** if there is a row (or the user explicitly approves a new `slug`).

---

## 5. Git sync workflow (placeholders)

Replace placeholders with values from §2 / memory.

### 5.1. First-time clone

```bash
mkdir -p "$WORK_ROOT/upstream"
cd "$WORK_ROOT/upstream"
git clone "$GIT_URL" "$CLONE_DIR"
```

### 5.2. Before editing upstream tree

```bash
cd "$WORK_ROOT/upstream/$CLONE_DIR"
git fetch origin
git pull --ff-only origin "$DEFAULT_BRANCH"
```

### 5.3. Branches

Avoid direct commits on the default branch unless the team agrees; prefer feature branches and human review for merges.

---

## 6. AI behaviour (Mia tech)

1. **Discover** paths and repos via **Agile Studio MCP**; if insufficient, **ask** the user, then **persist** answers in **`memory/MEMORY.md`** under **`## Project: …`** (§2).
2. **Read** this spec and **`PROJECT_INDEX.md`** (if present) before creating trees.
3. **Sync** with **`exec`** only when approved and paths are known; do not assume a clone already exists.
4. **Do not** commit secrets; respect `.gitignore`.
5. **Do not** `git push --force` to the agreed upstream remote unless an admin requests it in writing.
6. If **`restrictToWorkspace: true`**, `WORK_ROOT` must sit inside the allowed workspace or policy must allow the path (see **`../docs/TECH_SETUP.md`** under the `ai-tech/` deployment).

---

## 7. Relation to the agent platform repo

The repository that contains **Mia / nanobot** (this monorepo) is **tooling**. **Customer or programme repos** are **separate**; each project’s Git coordinates come from **§2**, not from any baked-in URL in agent prompts.

Optional **local-only** env (names illustrative; never commit secrets):

```env
# Example — set per machine / per environment after user or MCP defines targets
# WORK_ROOT=...
# GIT_URL=...
# DEFAULT_BRANCH=main
```

---

## 8. Acceptance checklist

- [ ] Clone URL and `WORK_ROOT` match **MCP + user + memory**, not a hard-coded default.
- [ ] `git remote -v` matches the intended canonical remote for this project.
- [ ] Each `projects/<slug>/` has `README.md` and slug matches the mapping table when used.
- [ ] No secret files committed.

---

## 9. Maintaining this document

| When | Action |
|------|--------|
| Tenant changes Hub field names | Update §2 to match Agile Studio / MCP docs. |
| New project | Add mapping row (§4), then create directories. |
| User gives new canonical URL | Update **`memory/MEMORY.md`** for that project. |

**Document version:** 1.4 — no fixed GitHub repo; MCP + user + `MEMORY.md`.
