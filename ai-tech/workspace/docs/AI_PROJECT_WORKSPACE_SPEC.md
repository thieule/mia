# Spec: Git sync and per-project / per-module directory layout

> **Location:** `workspace/docs/` — part of the **Mia tech** workspace (`./workspace` in config). The agent reads this file as `docs/AI_PROJECT_WORKSPACE_SPEC.md` (including when `restrictToWorkspace` is enabled).

This document defines **how Mia tech** should **pull code from Git**, **stay in sync** with the canonical remote, and **lay out child directories** so each directory maps to **one project or one module** in your system.

---

## 1. Purpose and scope

| Topic | Description |
|--------|-------------|
| **Goal** | A **predictable** directory tree, **traceable to Git**, for multi-project / multi-module work in one workspace. |
| **In scope** | Clone / pull / branches; naming rules; what the AI may or may not do without explicit approval. |
| **Out of scope** | Full CI/CD design, PR review policy (use team process docs). |

---

## 2. Canonical upstream repository

| Field | Value |
|--------|--------|
| **Git URL (HTTPS)** | `https://github.com/thieule/ai-repo.git` |
| **Role** | **Primary** repo for conventions, templates, or shared code; every working copy must be **traceable** to a commit on this remote. |
| **Notes** | If the remote URL changes or you use SSH (`git@github.com:thieule/ai-repo.git`), update this table and your env / sync scripts accordingly. |

---

## 3. Recommended directory layout (after sync)

**Principle:** one **clear clone** of upstream plus **separate child trees** per project/module (avoids mixing unrelated Git histories unless the team uses a monorepo).

### 3.1. Option A — Upstream clone + sibling `projects/` (recommended when using `exec`)

The working root (e.g. `WORK_ROOT`, may be an admin-defined path and **need not** live inside `workspace`):

```text
WORK_ROOT/
├── upstream/
│   └── ai-repo/                 # git clone https://github.com/thieule/ai-repo.git
│       ├── .git/
│       └── ...                  # upstream tree as cloned
└── projects/
    ├── <project-slug-1>/        # one directory = one project or module (unique id)
    │   ├── README.md            # required: purpose, ticket/ADR links, owner (link to docs/)
    │   ├── docs/                # documentation for this project/module only (see admin/DOCUMENTATION_AND_COMPLETION_CHECKLIST.md)
    │   │   └── ...
    │   └── ...
    ├── <module-slug-2>/
    │   ├── README.md
    │   ├── docs/
    │   └── ...
    └── ...
```

- **`upstream/ai-repo/`**: only content from `git clone` / `git pull` — the AI **must not** change the default `origin` remote unless an admin says so.
- **`projects/<slug>/`**: code or artefacts **per project/module**; `<slug>` matches the **project code** or **module code** in your system (lowercase letters, digits, hyphens; e.g. `billing-api`, `module-auth`). Each `<slug>` tree should include a **`docs/`** subfolder for that unit’s documentation and task **`COMPLETION_CHECKLIST.md`** files (see **`admin/DOCUMENTATION_AND_COMPLETION_CHECKLIST.md`**).

### 3.2. Option B — Submodule or subtree

If each project is its **own Git repo**, use **git submodule** or **subtree** under `projects/<slug>/`. Submodule details are owned by DevOps; the AI runs submodule/subtree commands **only** when the user or admin gives explicit instructions.

---

## 4. Mapping: system ↔ directories

The team maintains **one table** (e.g. `WORK_ROOT/PROJECT_INDEX.md` or internal wiki):

| Project / module ID (system) | Display name | Directory `slug` (`projects/…`) | Notes |
|------------------------------|----------------|-----------------------------------|--------|
| *(e.g. PRJ-001)* | *(e.g. Portal)* | `portal` | |
| *(e.g. MOD-AUTH)* | *(Auth)* | `module-auth` | |

The AI creates a **new** `projects/<slug>/` directory **only** if there is a row in this table (or the user explicitly approves a new `slug`).

---

## 5. Git sync workflow (AI and operators)

### 5.1. First-time setup (no clone yet)

```bash
mkdir -p WORK_ROOT/upstream
cd WORK_ROOT/upstream
git clone https://github.com/thieule/ai-repo.git ai-repo
```

### 5.2. Each session / before editing upstream code

```bash
cd WORK_ROOT/upstream/ai-repo
git fetch origin
git pull --ff-only origin <default-branch>
```

- **`<default-branch>`**: usually `main` or `develop` — document it in `PROJECT_INDEX.md` or `upstream/ai-repo/README.md`.

### 5.3. Working branches

- Direct commits on `main` are **discouraged**. For commits, use `feature/<slug>-<short-description>` when the user asks; merges go through human review.

---

## 6. AI behaviour (Mia tech)

1. **Read this spec** and `PROJECT_INDEX.md` (if present) before creating directory trees.
2. **Sync:** use the **`exec`** tool to run the commands in section 5 under the correct `WORK_ROOT` (or use read/write tools if the user already cloned and only needs `git pull`).
3. **Create `projects/<slug>/`:** only when the mapping table has a row or the user clearly approves a new `slug`; always add a **`README.md`** describing purpose and system links.
4. **Do not** commit secrets (`.env`, keys); verify `.gitignore` before `git add`.
5. **Do not** `git push --force` to `upstream/ai-repo` unless an admin requests it in writing.
6. If **`restrictToWorkspace: true`**, the agent may **not** reach `WORK_ROOT` outside the workspace — then `WORK_ROOT` must live **inside** the allowed workspace or policy must be adjusted (see `../docs/TECH_SETUP.md` under the `ai-tech/` deployment folder).

---

## 7. Relation to this monorepo (`mia`)

The **AI Agent** repo (e.g. `f:\workspace\a-agent\mia\…`) is the **tooling / agent platform**; **`ai-repo.git`** is your **business / project-layout** source. They are **independent** unless you add submodules or copy scripts.

Suggested **local-only** variables in `ai-tech/.env` (never commit):

```env
AI_REPO_WORK_ROOT=F:/workspace/ai-workspace
AI_REPO_UPSTREAM_URL=https://github.com/thieule/ai-repo.git
AI_REPO_DEFAULT_BRANCH=main
```

*(Names are suggestions — add to `EXAMPLE_.env` if the team standardises.)*

---

## 8. Acceptance checklist

- [ ] `upstream/ai-repo` is a clone of the URL in section 2; `git remote -v` matches.
- [ ] `git status` is clean or only has intentional changes before `pull`.
- [ ] Each `projects/<slug>/` has `README.md` and `slug` matches the mapping table.
- [ ] No secret files are committed to Git.

---

## 9. Maintaining this document

| When | Action |
|------|--------|
| Upstream URL changes | Update section 2 and env / scripts. |
| New project | Add a row to section 4, then create the directory. |
| Default branch changes | Update section 5.2 and notify the team. |

**Document version:** 1.3 — English rewrite; file lives under `workspace/docs/` (Mia tech only).
