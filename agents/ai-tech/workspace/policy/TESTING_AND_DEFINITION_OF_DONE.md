# Unit tests, pytest, and definition of “done” (Mia tech)

**Status:** Human-maintained policy under `policy/`. Mia tech **must read and follow** this file. It **must not** edit files in `policy/` without an approved workflow.

---

## 1. Purpose

Every **code change** that Mia tech introduces or materially edits must ship with **automated tests**, and **pytest must be executed** before the assistant tells the user the work is **done**, **complete**, or equivalent.

---

## 2. When unit tests are required

| Change type | Unit tests |
|-------------|------------|
| **New** functions, classes, modules, or services (application / library code) | **Required** — add or extend `unittest` / `pytest` style tests following the **existing project layout** (e.g. `tests/`, `test_*.py`). |
| **Non-trivial** edits to behaviour (bug fix, refactor that changes contracts) | **Required** — update or add tests proving old/new behaviour. |
| **Docs-only**, comments, formatting with **no** semantic change | Tests **not** required unless project policy says otherwise; still **run pytest** if the repo’s CI would run on the touched paths. |
| **Config / infra** (YAML, Docker) with runtime impact | Add or run tests that the repo already uses for validation; if none exist, **state the gap** and run the **closest** pytest suite (e.g. smoke import). |

If the repository uses a **different** primary test runner, follow that convention but **still** run **`pytest`** when the tree includes pytest-discoverable tests (many Python repos expose both).

---

## 3. Running pytest before reporting “done”

Before any message that claims the task is **finished**, **done**, **ready for review**, **shipped**, or similar:

1. **Run pytest** on the **smallest relevant scope** (single file, package, or whole suite per project norms):
   - Prefer **`mcp_pytest_runner_*`** when configured; or
   - **`exec`** with the project’s standard command (e.g. `python -m pytest path/to/tests -q`).
2. **Report** in the same turn (or immediately after tool output):
   - **Pass/fail** summary (and `run_id` if using pytest MCP).
   - If **failures**: **do not** claim done — fix or explain blockers, then re-run until green **or** stop with an explicit **blocked** status and what the user must do.
3. If **pytest cannot run** (missing deps, wrong interpreter, no tests yet): **do not** claim done — say **blocked**, list what is missing, and what tests **should** exist once unblocked.

**Wording rule:** Do not use “done / complete / finished” for implementation work until **pytest has succeeded** for the agreed scope (or §4 exception applies) **and** **`policy/DOCUMENTATION_AND_COMPLETION_CHECKLIST.md`** is satisfied (docs updated + completion checklist written).

---

## 4. Exceptions (admin-maintained)

List **only** what admins allow without pytest evidence:

- *(None by default.)*

If this list is empty, **no exceptions** — §3 applies to all implementation completions.

---

## 5. Cross-references

See **`policy/README.md`**. **Approve → implement (with tests) → pytest → docs + checklist → report → “done”.**
