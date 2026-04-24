# Pre-implementation admin approval (Mia QC)

**Status:** Human-maintained policy under `admin/`. Mia QC **must read and follow** this file. It **must not** edit files in `admin/` without an approved workflow.

---

## 1. Purpose

Reduce risk from autonomous coding: **no implementation that changes repositories, installs software, or runs mutating shell commands** until an **admin** has **explicitly approved** the plan in writing.

---

## 2. When this gate applies (hard stop)

Before using any of the following, the agent **must** obtain **admin approval** as in §4:

| Tool / action | Gate applies |
|---------------|----------------|
| **`write_file`** | Yes — new or replaced files in the repo or `WORK_ROOT` (see `docs/AI_PROJECT_WORKSPACE_SPEC.md`). |
| **`edit_file`** | Yes — any patch to tracked or production code. |
| **`notebook_edit`** | Yes — if it changes notebook content used as source or product. |
| **`exec`** | Yes — if the command can **change state**: `git commit`, `git push`, package install/upgrade, migrations, `rm`, formatters that rewrite many files, test runs that write outside scratch, etc. |
| **`spawn`** | Yes — when the subagent’s task is to **implement, refactor, or fix** code (not read-only research). |

**Does not require this gate** (unless the team extends policy):

- **`read_file`**, **`grep`**, **`glob`**, **`list_dir`** — analysis and navigation.
- **`web_search`**, **`web_fetch`** — research.
- **Diagrams and prose** in the reply only (no tool writes).
- **`exec`** for **read-only** inspection: e.g. `git status`, `git log -1`, `git diff` (no write flags), `ls`, one-off `cat`/`head` where policy allows.

If unsure whether an `exec` is mutating: **treat it as gated** and ask.

---

## 3. Who counts as an admin

**Source of truth:**

- **`config/config.json`** → `channels.discord.adminUserIds` (from env, e.g. `DISCORD_ADMIN_USER_IDS` in `ai-qc/.env`).
- Those values are **Discord user snowflake IDs** when Discord is enabled.

**CLI / API-only sessions (no Discord):**

- The team should list **who may approve** in `admin/README.md` (names + email or internal id) or require approval in the **same thread** from an account the team treats as admin.
- Until that is documented, the agent **must** ask the user to name an approver or paste **explicit written approval** from a documented maintainer; if unclear, **do not implement**.

---

## 4. What counts as approval

**Sufficient (examples):**

- `"Approved: <one-line summary of what may change>"` from a user whose Discord id is in `adminUserIds`.
- Same, from a documented maintainer in `admin/README.md` for non-Discord channels.

**Insufficient (ask again or stay in plan-only mode):**

- `"ok"`, `"go ahead"`, `"sounds good"` **without** tying to a concrete plan when multiple options were proposed.
- Approval from a user **not** in `adminUserIds` / not listed as maintainer.

**Ambiguous scope:** ask one short follow-up (e.g. “Approve **only** files under `a-tools/registry/` or the whole PR?”). Until clarified → **not approved**.

---

## 5. Required flow (agent)

1. **Summarise** the proposed change: goal, main files/commands, risks, rollback idea (if any).
2. **Ask** specifically for **admin approval** for that scope (mention @ admin on Discord if the channel supports it, or ask the user to forward to a maintainer).
3. **Wait** for §4-quality confirmation in the **same session** (or team-defined handoff).
4. **Only then** call `write_file` / `edit_file` / mutating `exec` / implementation **`spawn`**.
5. If approval never arrives: deliver **design / steps only**; do not mutate code.

---

## 6. Exceptions

Document exceptions here (human-edited):

- *(None by default.)*

If this section is empty, **no exceptions** — the gate always applies for §2.

---

## 7. Relation to other policy

- **`admin/README.md`** — index of admin files; list named approvers for non-Discord setups.
- **`admin/TESTING_AND_DEFINITION_OF_DONE.md`** — after approved implementation: **unit tests + pytest** before claiming work is **done** (separate mandatory gate).
- **`admin/DOCUMENTATION_AND_COMPLETION_CHECKLIST.md`** — **docs + completion checklist** (and per-slug **`docs/`**) before “done”.
- **`admin/CODE_COMMENTS_AND_ERRORS_ENGLISH.md`** — **English** for code, errors/logs, and **policy-driven repo documentation**.
- **`docs/AI_PROJECT_WORKSPACE_SPEC.md`** — layout for `ai-repo` / `projects/`; still subject to this approval gate before creating or changing those trees unless an admin pre-approved a standing rule below.

**Standing bulk approvals** (optional, admin-maintained):

- *(e.g. “Approved class of change: typo fixes only in `workspace/agent/` until revoked.”)*

If nothing is listed, there are **no** standing bulk approvals.
